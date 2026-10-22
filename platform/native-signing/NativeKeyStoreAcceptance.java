import org.karnatakadbt.crypto.NativeEncryptedKeyStore;
import io.mosip.kernel.core.keymanager.model.CertificateParameters;
import java.util.*;
import java.security.*;
import java.time.LocalDateTime;
import java.nio.file.*;
import javax.crypto.*;

/** Isolated synthetic vault acceptance. Never opens a production vault. */
public class NativeKeyStoreAcceptance {
 public static void main(String[] args)throws Exception {
  Map<String,String> config=new HashMap<>();config.put("directory",args[0]);config.put("scope","acceptance");
  NativeEncryptedKeyStore vault=new NativeEncryptedKeyStore(config);
  // Exercise the real Spring configuration binding and upstream factory, not
  // just direct construction. The factory exposes setJce, rather than setJceParams.
  Map<String,String> properties=new HashMap<>();String prefix="mosip.kernel.keymanager.hsm";
  properties.put(prefix+".jce.className","org.karnatakadbt.crypto.NativeEncryptedKeyStore");properties.put(prefix+".jce.directory",args[0]);properties.put(prefix+".jce.scope","acceptance");
  io.mosip.kernel.keymanager.hsm.impl.KeyStoreImpl factory=new io.mosip.kernel.keymanager.hsm.impl.KeyStoreImpl();
  new org.springframework.boot.context.properties.bind.Binder(new org.springframework.boot.context.properties.source.MapConfigurationPropertySource(properties)).bind(prefix,org.springframework.boot.context.properties.bind.Bindable.ofInstance(factory));
  java.lang.reflect.Field type=factory.getClass().getDeclaredField("keystoreType");type.setAccessible(true);type.set(factory,"NATIVE");
  factory.afterPropertiesSet();if(!factory.getAllAlias().isEmpty())throw new AssertionError("factory bound wrong vault");
  CertificateParameters params=new CertificateParameters();params.setNotBefore(LocalDateTime.now().minusMinutes(1));params.setNotAfter(LocalDateTime.now().plusDays(2));
  vault.generateAndStoreAsymmetricKey("root","",params);vault.generateAndStoreAsymmetricKey("signer","root",params);
  vault.getCertificate("signer").verify(vault.getPublicKey("root"));
  byte[] message="synthetic signing acceptance".getBytes("UTF-8");Signature sig=Signature.getInstance("SHA256withRSA");sig.initSign(vault.getPrivateKey("signer"));sig.update(message);byte[] signed=sig.sign();sig.initVerify(vault.getPublicKey("signer"));sig.update(message);if(!sig.verify(signed))throw new AssertionError();
  vault.storeCertificate("historical",null,vault.getCertificate("signer"));boolean refused=false;try{vault.getPrivateKey("historical");}catch(IllegalStateException expected){refused=true;}if(!refused)throw new AssertionError("public key used privately");
  refused=false;try{vault.storeCertificate("mismatch",vault.getPrivateKey("root"),vault.getCertificate("signer"));}catch(IllegalStateException expected){refused=true;}if(!refused)throw new AssertionError("mismatched certificate accepted");
  vault.generateAndStoreSymmetricKey("aes");Cipher c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.ENCRYPT_MODE,vault.getSymmetricKey("aes"));byte[] iv=c.getIV(),sealed=c.doFinal(message);c.init(Cipher.DECRYPT_MODE,vault.getSymmetricKey("aes"),new javax.crypto.spec.GCMParameterSpec(128,iv));if(!Arrays.equals(message,c.doFinal(sealed)))throw new AssertionError();
  NativeEncryptedKeyStore reopened=new NativeEncryptedKeyStore(config);if(reopened.getAllAlias().size()!=4)throw new AssertionError("persistence failed");
  java.util.concurrent.ExecutorService pool=java.util.concurrent.Executors.newFixedThreadPool(4);List<java.util.concurrent.Future<?>> results=new ArrayList<>();for(int i=0;i<12;i++){final int n=i;results.add(pool.submit(()->new NativeEncryptedKeyStoreUnchecked(config).store.generateAndStoreSymmetricKey("concurrent-"+n)));}for(java.util.concurrent.Future<?> f:results)f.get();pool.shutdown();if(vault.getAllAlias().size()!=16)throw new AssertionError("lost concurrent writes");
  Path file=Paths.get(args[0],"vault.bin");byte[] pristine=Files.readAllBytes(file),tampered=pristine.clone();tampered[tampered.length-1]^=1;Files.write(file,tampered);refused=false;try{new NativeEncryptedKeyStore(config);}catch(Exception expected){refused=true;}finally{Files.write(file,pristine);}if(!refused)throw new AssertionError("tampered vault accepted");
  byte[] master=Files.readAllBytes(Paths.get(args[0],"master.key"));byte[] wrong=master.clone();wrong[0]^=1;Files.write(Paths.get(args[0],"master.key"),wrong);refused=false;try{new NativeEncryptedKeyStore(config);}catch(Exception expected){refused=true;}finally{Files.write(Paths.get(args[0],"master.key"),master);}if(!refused)throw new AssertionError("wrong master accepted");
  if(new NativeEncryptedKeyStore(config).getAllAlias().size()!=16)throw new AssertionError("recovery failed");
  System.out.println("{\"passed\":true,\"signing\":true,\"certificate_chain\":true,\"public_only_enforced\":true,\"mismatch_rejected\":true,\"aes_roundtrip\":true,\"persistence\":true,\"concurrent_writes\":true,\"tamper_rejected\":true,\"wrong_master_rejected\":true,\"recovery\":true}");
 }
 static class NativeEncryptedKeyStoreUnchecked {final NativeEncryptedKeyStore store;NativeEncryptedKeyStoreUnchecked(Map<String,String> p){try{store=new NativeEncryptedKeyStore(p);}catch(Exception e){throw new RuntimeException(e);}}}
}
