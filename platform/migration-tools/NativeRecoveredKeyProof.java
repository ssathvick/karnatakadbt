import java.nio.file.*;
import java.security.*;
import java.security.cert.Certificate;
import java.util.*;

/** Prove possession in the already recovered PKCS12, without exporting keys. */
public class NativeRecoveredKeyProof {
    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new SecurityException("Private directory required");
        Path folder=Path.of(args[0]).toRealPath();
        if (!folder.startsWith(Path.of("/opt/karnatakadbt/private/mosip-migration/remaining-three"))) throw new SecurityException("Scope");
        Security.addProvider((Provider)Class.forName("org.bouncycastle.jce.provider.BouncyCastleProvider").getConstructor().newInstance());
        byte[] expected=Files.readAllBytes(folder.resolve("expected-private-certificates.tsv"));
        if(expected.length>2*1024*1024)throw new SecurityException("Bound");
        char[] password=Files.readString(folder.resolve("p12-password")).toCharArray();
        KeyStore store=KeyStore.getInstance("PKCS12");
        try(var in=Files.newInputStream(folder.resolve("recovered.p12"))){store.load(in,password);}
        int count=0;Set<String> seen=new HashSet<>();
        for(String line:new String(expected,java.nio.charset.StandardCharsets.UTF_8).split("\\n")){
            if(line.isEmpty())continue;
            String[] fields=line.split("\\t",-1);
            if(fields.length!=2 || !fields[0].matches("[A-Za-z0-9_.:-]{1,256}") || !fields[1].matches("[a-f0-9]{64}") || !seen.add(fields[0]))throw new SecurityException("Inventory");
            Certificate cert=store.getCertificate(fields[0]);
            Key key=store.getKey(fields[0],password);
            if(cert==null || !(key instanceof PrivateKey) || !HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(cert.getEncoded())).equals(fields[1]))throw new SecurityException("Material differs");
            String algorithm=key.getAlgorithm();
            String scheme=algorithm.equals("RSA")?"SHA256withRSA":algorithm.equals("EC")?"SHA256withECDSA":"Ed25519";
            byte[] challenge=new byte[32];new SecureRandom().nextBytes(challenge);
            Signature signer=Signature.getInstance(scheme,"BC");signer.initSign((PrivateKey)key);signer.update(challenge);byte[] signature=signer.sign();
            signer.initVerify(cert.getPublicKey());signer.update(challenge);
            if(!signer.verify(signature))throw new SecurityException("Possession");
            count++;
        }
        if(count<1)throw new SecurityException("Empty inventory");
        Arrays.fill(password,'\0');System.out.println(count);
    }
}
