package org.karnatakadbt.crypto;

import io.mosip.kernel.core.keymanager.spi.KeyStore;
import io.mosip.kernel.core.keymanager.model.CertificateParameters;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.core.type.TypeReference;
import java.nio.file.*;
import java.nio.channels.*;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.security.spec.PKCS8EncodedKeySpec;
import java.security.cert.*;
import java.math.BigInteger;
import java.time.ZoneOffset;
import java.util.*;
import java.io.*;
import javax.crypto.*;
import javax.crypto.spec.*;
import org.bouncycastle.jce.provider.BouncyCastleProvider;
import org.bouncycastle.asn1.x500.X500Name;
import org.bouncycastle.asn1.x500.X500NameBuilder;
import org.bouncycastle.asn1.x500.style.BCStyle;
import org.bouncycastle.cert.jcajce.JcaX509v3CertificateBuilder;
import org.bouncycastle.cert.jcajce.JcaX509CertificateConverter;
import org.bouncycastle.operator.jcajce.JcaContentSignerBuilder;
import org.bouncycastle.asn1.x509.BasicConstraints;
import org.bouncycastle.asn1.x509.KeyUsage;

/** Software vault compatibility boundary. No PKCS11 library/socket or fallback. */
public final class NativeEncryptedKeyStore implements KeyStore {
 private final Path directory,file; private final byte[] master,aad;
 private static final ObjectMapper JSON=new ObjectMapper();
 private static final SecureRandom RANDOM=new SecureRandom();
 private static final Map<String,Object> LOCKS=new HashMap<>();private final Object lock;
 public NativeEncryptedKeyStore(Map<String,String> params)throws Exception{
  String path=params.get("directory"),scope=params.get("scope");
  if(path==null||scope==null||!path.startsWith("/"))throw new SecurityException("Native vault configuration required");
  directory=Paths.get(path).toRealPath();file=directory.resolve("vault.bin");master=Files.readAllBytes(directory.resolve("master.key"));
  if(master.length!=32)throw new SecurityException("AES-256 wrapping key required");
  aad=("native-java-keystore-v1:"+scope).getBytes(StandardCharsets.UTF_8);
  synchronized(LOCKS){lock=LOCKS.computeIfAbsent(directory.toString(),k->new Object());}
  if(Security.getProvider("BC")==null)Security.addProvider(new BouncyCastleProvider());
  synchronized(lock){read();} // Existing authenticated vault required; never create empty replacements.
 }
 private Map<String,Map<String,String>> read()throws Exception{
  byte[] raw=Files.readAllBytes(file);if(raw.length<28)throw new SecurityException("Invalid native vault");
  Cipher c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.DECRYPT_MODE,new SecretKeySpec(master,"AES"),new GCMParameterSpec(128,Arrays.copyOfRange(raw,0,12)));c.updateAAD(aad);
  return JSON.readValue(c.doFinal(Arrays.copyOfRange(raw,12,raw.length)),new TypeReference<Map<String,Map<String,String>>>(){});
 }
 private void write(Map<String,Map<String,String>> values)throws Exception{
  byte[] nonce=new byte[12];RANDOM.nextBytes(nonce);Cipher c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.ENCRYPT_MODE,new SecretKeySpec(master,"AES"),new GCMParameterSpec(128,nonce));c.updateAAD(aad);byte[] sealed=c.doFinal(JSON.writeValueAsBytes(values));
  Path tmp=Files.createTempFile(directory,"vault-",".next");
  try{
   Files.setPosixFilePermissions(tmp,java.nio.file.attribute.PosixFilePermissions.fromString("rw-------"));
   try(FileChannel out=FileChannel.open(tmp,StandardOpenOption.WRITE)){ByteBuffer b=ByteBuffer.allocate(nonce.length+sealed.length).put(nonce).put(sealed);b.flip();while(b.hasRemaining())out.write(b);out.force(true);}
   Files.move(tmp,file,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
   try(FileChannel dir=FileChannel.open(directory,StandardOpenOption.READ)){dir.force(true);}
  }finally{Files.deleteIfExists(tmp);}
 }
 private interface Operation<T>{T apply(Map<String,Map<String,String>> entries)throws Exception;}
 private <T>T operate(boolean mutate,Operation<T> op){synchronized(lock){
  try(FileChannel channel=FileChannel.open(directory.resolve("vault.lock"),StandardOpenOption.CREATE,StandardOpenOption.WRITE);FileLock ignored=channel.lock()){
   Files.setPosixFilePermissions(directory.resolve("vault.lock"),java.nio.file.attribute.PosixFilePermissions.fromString("rw-------"));
   Map<String,Map<String,String>> entries=read();T result=op.apply(entries);if(mutate)write(entries);return result;
  }catch(Exception ex){throw new IllegalStateException("Native vault operation failed",ex);}
 }}
 private static void alias(String alias){if(alias==null||alias.isEmpty()||alias.length()>256)throw new SecurityException("Invalid key alias");}
 private static Map<String,String> entry(Map<String,Map<String,String>> entries,String alias){alias(alias);Map<String,String> e=entries.get(alias);if(e==null)throw new SecurityException("Key alias unavailable");return e;}
 private static PrivateKey privateKey(Map<String,String> e)throws Exception{if(!e.containsKey("private"))throw new SecurityException("Verification-only alias");return KeyFactory.getInstance("RSA").generatePrivate(new PKCS8EncodedKeySpec(Base64.getDecoder().decode(e.get("private"))));}
 private static X509Certificate certificate(Map<String,String> e)throws Exception{return (X509Certificate)CertificateFactory.getInstance("X.509").generateCertificate(new ByteArrayInputStream(Base64.getDecoder().decode(e.get("certificate"))));}
 public PrivateKey getPrivateKey(String alias){return operate(false,e->privateKey(entry(e,alias)));}
 public PublicKey getPublicKey(String alias){return getCertificate(alias).getPublicKey();}
 public java.security.cert.Certificate getCertificate(String alias){return operate(false,e->certificate(entry(e,alias)));}
 public SecretKey getSymmetricKey(String alias){return operate(false,all->{Map<String,String> e=entry(all,alias);if(!e.containsKey("secret"))throw new SecurityException("AES alias required");return new SecretKeySpec(Base64.getDecoder().decode(e.get("secret")),"AES");});}
 public java.security.KeyStore.PrivateKeyEntry getAsymmetricKey(String alias){return operate(false,all->{Map<String,String> e=entry(all,alias);return new java.security.KeyStore.PrivateKeyEntry(privateKey(e),new java.security.cert.Certificate[]{certificate(e)});});}
 public List<String> getAllAlias(){return operate(false,e->new ArrayList<>(e.keySet()));}
 public Key getKey(String alias){return operate(false,all->{Map<String,String> e=entry(all,alias);return e.containsKey("secret")?new SecretKeySpec(Base64.getDecoder().decode(e.get("secret")),"AES"):privateKey(e);});}
 public String getKeystoreProviderName(){return "BC";}
 public void generateAndStoreSymmetricKey(String alias){alias(alias);operate(true,all->{if(all.containsKey(alias))throw new SecurityException("Alias cannot be overwritten");byte[] key=new byte[32];RANDOM.nextBytes(key);Map<String,String> e=new HashMap<>();e.put("secret",Base64.getEncoder().encodeToString(key));all.put(alias,e);return null;});}
 public void generateAndStoreAsymmetricKey(String alias,String signerAlias,CertificateParameters params){alias(alias);operate(true,all->{
  if(all.containsKey(alias))throw new SecurityException("Alias cannot be overwritten");KeyPairGenerator generator=KeyPairGenerator.getInstance("RSA");generator.initialize(3072,RANDOM);KeyPair pair=generator.generateKeyPair();
  X500NameBuilder subjectBuilder=new X500NameBuilder(BCStyle.INSTANCE);
  subjectBuilder.addRDN(BCStyle.CN,params.getCommonName()==null?"KarnatakaDBT Native "+alias:params.getCommonName());
  if(params.getOrganization()!=null)subjectBuilder.addRDN(BCStyle.O,params.getOrganization());
  if(params.getOrganizationUnit()!=null)subjectBuilder.addRDN(BCStyle.OU,params.getOrganizationUnit());
  if(params.getCountry()!=null)subjectBuilder.addRDN(BCStyle.C,params.getCountry());
  if(params.getState()!=null)subjectBuilder.addRDN(BCStyle.ST,params.getState());
  if(params.getLocation()!=null)subjectBuilder.addRDN(BCStyle.L,params.getLocation());
  X500Name subject=subjectBuilder.build();PrivateKey signer=pair.getPrivate();X500Name issuer=subject;boolean root=signerAlias==null||signerAlias.isEmpty()||signerAlias.equals(alias);
  if(!root){Map<String,String> parent=entry(all,signerAlias);signer=privateKey(parent);issuer=new X500Name(certificate(parent).getSubjectX500Principal().getName());}
  Date start=Date.from(params.getNotBefore().toInstant(ZoneOffset.UTC)),end=Date.from(params.getNotAfter().toInstant(ZoneOffset.UTC));
  JcaX509v3CertificateBuilder b=new JcaX509v3CertificateBuilder(issuer,new BigInteger(159,RANDOM).add(BigInteger.ONE),start,end,subject,pair.getPublic());
  b.addExtension(org.bouncycastle.asn1.x509.Extension.basicConstraints,true,new BasicConstraints(root));b.addExtension(org.bouncycastle.asn1.x509.Extension.keyUsage,true,new KeyUsage(root?KeyUsage.keyCertSign|KeyUsage.cRLSign:KeyUsage.digitalSignature|KeyUsage.keyEncipherment));
  X509Certificate cert=new JcaX509CertificateConverter().setProvider("BC").getCertificate(b.build(new JcaContentSignerBuilder("SHA256withRSA").setProvider("BC").build(signer)));
  Map<String,String> value=new HashMap<>();value.put("private",Base64.getEncoder().encodeToString(pair.getPrivate().getEncoded()));value.put("certificate",Base64.getEncoder().encodeToString(cert.getEncoded()));all.put(alias,value);return null;
 });}
 public void deleteKey(String alias){operate(true,all->{entry(all,alias);all.remove(alias);return null;});}
 public void storeCertificate(String alias,PrivateKey privateKey,java.security.cert.Certificate cert){alias(alias);operate(true,all->{
  if(!"RSA".equals(cert.getPublicKey().getAlgorithm()))throw new SecurityException("RSA certificate required");
  if(privateKey!=null){byte[] proof=new byte[32];RANDOM.nextBytes(proof);Signature sign=Signature.getInstance("SHA256withRSA");sign.initSign(privateKey);sign.update(proof);byte[] sig=sign.sign();sign.initVerify(cert.getPublicKey());sign.update(proof);if(!sign.verify(sig))throw new SecurityException("Certificate does not match private key");}
  Map<String,String> value=new HashMap<>();value.put("certificate",Base64.getEncoder().encodeToString(cert.getEncoded()));if(privateKey!=null)value.put("private",Base64.getEncoder().encodeToString(privateKey.getEncoded()));
  else if(all.containsKey(alias)&&all.get(alias).containsKey("private"))throw new SecurityException("Cannot replace a private alias with a public-only entry");
  all.put(alias,value);return null;
 });}
}
