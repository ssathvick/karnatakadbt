import java.io.*;
import java.nio.file.*;
import java.security.*;
import java.security.cert.Certificate;
import java.security.cert.CertificateFactory;
import java.security.spec.PKCS8EncodedKeySpec;
import java.util.*;
import javax.crypto.*;
import javax.crypto.spec.*;

/** Generic JCA recovery utility. No MOSIP business classes are loaded. */
public class NativeCertifyKeyRecovery {
    static byte[] bytes(DataInputStream in) throws Exception {
        int length = in.readInt();
        if (length < 0 || length > 1024 * 1024) throw new SecurityException("Recovery field bound");
        byte[] result = in.readNBytes(length);
        if (result.length != length) throw new EOFException();
        return result;
    }
    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new SecurityException("Explicit private recovery directory required");
        Path folder = Path.of(args[0]).toRealPath();
        if (!folder.toString().startsWith("/opt/karnatakadbt/private/mosip-migration/remaining-three/")) throw new SecurityException("Recovery scope mismatch");
        Security.addProvider((Provider)Class.forName("org.bouncycastle.jce.provider.BouncyCastleProvider").getConstructor().newInstance());
        byte[] key = Files.readAllBytes(folder.resolve("transfer.key"));
        byte[] sealed = Files.readAllBytes(folder.resolve("material.bin"));
        if (key.length != 32 || sealed.length < 28 || sealed.length > 32*1024*1024) throw new SecurityException("Bounded authenticated input required");
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE,new SecretKeySpec(key,"AES"),new GCMParameterSpec(128,sealed,0,12));
        cipher.updateAAD("kdbt-certify-pkcs12-recovery-v1".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        char[] password = Files.readString(folder.resolve("p12-password")).toCharArray();
        KeyStore store = KeyStore.getInstance("PKCS12");store.load(null,password);
        Map<String,byte[]> publicKeys = new TreeMap<>(), secrets = new TreeMap<>();
        Set<String> aliases = new HashSet<>();
        try (DataInputStream in = new DataInputStream(new ByteArrayInputStream(cipher.doFinal(sealed,12,sealed.length-12)))) {
            if (!in.readUTF().equals("KDBT-CERTIFY-KEYS-V1")) throw new SecurityException("Recovery version mismatch");
            int count = in.readInt();
            if (count < 1 || count > 10000) throw new SecurityException("Alias count bound");
            CertificateFactory factory = CertificateFactory.getInstance("X.509");
            for (int i=0;i<count;i++) {
                String alias = in.readUTF(), algorithm = in.readUTF();int kind = in.readInt();
                if (!alias.matches("[A-Za-z0-9_.:-]{1,256}") || !aliases.add(alias.toLowerCase(Locale.ROOT))) throw new SecurityException("Alias collision");
                byte[] material = bytes(in);int chainLength = in.readInt();
                if (chainLength < 0 || chainLength > 32) throw new SecurityException("Certificate chain bound");
                Certificate[] chain = new Certificate[chainLength];
                for (int j=0;j<chainLength;j++) chain[j] = factory.generateCertificate(new ByteArrayInputStream(bytes(in)));
                if (kind == 1) {
                    if (!Set.of("RSA","EC","Ed25519").contains(algorithm) || chainLength < 1) throw new SecurityException("Private-key metadata mismatch");
                    PrivateKey privateKey = KeyFactory.getInstance(algorithm,"BC").generatePrivate(new PKCS8EncodedKeySpec(material));
                    store.setKeyEntry(alias,privateKey,password,chain);publicKeys.put(alias,chain[0].getPublicKey().getEncoded());
                } else if (kind == 2) {
                    if (!algorithm.equals("AES") || chainLength != 0 || !Set.of(16,24,32).contains(material.length)) throw new SecurityException("Symmetric metadata mismatch");
                    store.setEntry(alias,new KeyStore.SecretKeyEntry(new SecretKeySpec(material,"AES")),new KeyStore.PasswordProtection(password));
                    secrets.put(alias,material);
                } else if (kind == 3) {
                    if (material.length != 0 || chainLength != 1) throw new SecurityException("Public certificate metadata mismatch");
                    store.setCertificateEntry(alias,chain[0]);publicKeys.put(alias,chain[0].getPublicKey().getEncoded());
                } else throw new SecurityException("Unknown key kind");
            }
            if (in.read() != -1) throw new SecurityException("Trailing recovery data");
        }
        Path pending = folder.resolve("recovered.p12.pending"), output = folder.resolve("recovered.p12");
        if (Files.exists(output) || Files.exists(pending)) throw new SecurityException("Existing recovery archive must be retained");
        try (OutputStream out = Files.newOutputStream(pending,StandardOpenOption.CREATE_NEW)) { store.store(out,password); }
        KeyStore reopened = KeyStore.getInstance("PKCS12");
        try (InputStream in = Files.newInputStream(pending)) { reopened.load(in,password); }
        if (reopened.size() != aliases.size()) throw new SecurityException("Recovered alias count mismatch");
        int verified = 0;
        for (String alias : publicKeys.keySet()) {
            Certificate cert = reopened.getCertificate(alias);
            if (!MessageDigest.isEqual(cert.getPublicKey().getEncoded(),publicKeys.get(alias))) throw new SecurityException("Recovered public key mismatch");
            Key restored = reopened.getKey(alias,password);
            if (restored instanceof PrivateKey) {
                String algorithm = restored.getAlgorithm();
                String signatureAlgorithm = algorithm.equals("RSA") ? "SHA256withRSA" : algorithm.equals("EC") ? "SHA256withECDSA" : "Ed25519";
                byte[] challenge = new byte[32];new SecureRandom().nextBytes(challenge);
                Signature signature = Signature.getInstance(signatureAlgorithm,"BC");signature.initSign((PrivateKey)restored);signature.update(challenge);byte[] signed=signature.sign();
                signature.initVerify(cert.getPublicKey());signature.update(challenge);
                if (!signature.verify(signed)) throw new SecurityException("Recovered private-key challenge failed");
                verified++;
            }
        }
        for (String alias : secrets.keySet())
            if (!MessageDigest.isEqual(reopened.getKey(alias,password).getEncoded(),secrets.get(alias))) throw new SecurityException("Recovered symmetric key mismatch");
        Files.move(pending,output,StandardCopyOption.ATOMIC_MOVE);
        System.out.println("{\"aliases\":"+aliases.size()+",\"private_keys_verified\":"+verified+",\"symmetric_keys_verified\":"+secrets.size()+",\"reopened_pkcs12_verified\":true}");
        Arrays.fill(key,(byte)0);Arrays.fill(password,'\0');
    }
}
